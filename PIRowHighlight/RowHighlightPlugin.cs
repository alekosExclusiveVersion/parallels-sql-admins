using System;
using System.Drawing;
using System.Windows.Forms;
using DevExpress.XtraGrid.Views.Grid;
using Tradesoft.Autovision;

namespace PIRowHighlight
{
    public class RowHighlightPlugin : IPlugin
    {
        public string Caption { get; set; }

        public RowHighlightPlugin()
        {
            Caption = "Подсветка остатков в позициях документа";
        }

        public void InitPlugin(User currentUser)
        {
            RegisterFor(typeof(DicJournalDetails));
            RegisterFor(typeof(DicMoveDetails));
            RegisterFor(typeof(DicChargeCorrection.DicJournalDetailsForChargeCorrection));
            RegisterFor(typeof(DicReceiptCorrection.DicJournalDetailsForReceiptCorrection));
        }

        private static void RegisterFor(Type detailsDictionaryType)
        {
            BizDictionary.RegisterColumnPlugin(detailsDictionaryType, gridView =>
            {
                gridView.RowStyle += OnDetailsRowStyle;
            });
        }

        private static void OnDetailsRowStyle(object sender, RowStyleEventArgs e)
        {
            if (e.RowHandle < 0)
            {
                return;
            }

            try
            {
                GridView gridView = sender as GridView;
                if (gridView == null)
                {
                    return;
                }

                JournalItem item = UnwrapRow(gridView.GetRow(e.RowHandle)) as JournalItem;
                if (item == null || item.Ware == null || item.IsDeleted || item.Amount <= 0m)
                {
                    return;
                }

                if (item.TotalRest < item.Amount)
                {
                    e.Appearance.BackColor = Color.LightCoral;
                    e.Appearance.ForeColor = Color.DarkRed;
                }
            }
            catch
            {
            }
        }

        private static object UnwrapRow(object row)
        {
            if (row == null)
            {
                return null;
            }

            if (row.GetType().Name.StartsWith("ReadonlyThreadSafeProxy"))
            {
                System.Reflection.PropertyInfo originalRow = row.GetType().GetProperty("OriginalRow");
                return originalRow != null ? originalRow.GetValue(row, null) : null;
            }

            return row;
        }
    }
}
